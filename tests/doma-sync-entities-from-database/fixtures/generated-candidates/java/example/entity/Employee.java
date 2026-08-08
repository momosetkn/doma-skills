package example.entity;

import org.seasar.doma.Column;
import org.seasar.doma.Entity;
import org.seasar.doma.GeneratedValue;
import org.seasar.doma.GenerationType;
import org.seasar.doma.Id;
import org.seasar.doma.Metamodel;
import org.seasar.doma.Table;
import org.seasar.doma.Version;

/** Employees */
@Entity(metamodel = @Metamodel)
@Table(schema = "public", name = "employee")
public class Employee {

    /** Employee ID */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "employee_id")
    Integer id;

    /** Display name */
    @Column(name = "display_name")
    String displayName;

    /** */
    @Version
    @Column(name = "version")
    Integer version;

    /** Returns the id. */
    public Integer getId() {
        return id;
    }

    /** Sets the id. */
    public void setId(Integer id) {
        this.id = id;
    }

    /** Returns the displayName. */
    public String getDisplayName() {
        return displayName;
    }

    /** Sets the displayName. */
    public void setDisplayName(String displayName) {
        this.displayName = displayName;
    }

    /** Returns the version. */
    public Integer getVersion() {
        return version;
    }

    /** Sets the version. */
    public void setVersion(Integer version) {
        this.version = version;
    }
}
